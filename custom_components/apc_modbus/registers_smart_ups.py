# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Shared register definitions for Smart-UPS devices.

Based on 990-5702A-EN (Smart-UPS excluding SMT/SMX/SURTD/SRT).
Addresses are Modbus wire addresses (register number - 40000 for holding registers).
"""

REGISTERS = [
    # Status Words
    {
        "key": "status_word_0",
        "address": 0x0000,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "status_word_1",
        "address": 0x0001,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "status_word_2",
        "address": 0x0002,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "status_word_3",
        "address": 0x0003,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Line Quality & Battery
    {
        "key": "line_quality",
        "address": 0x0004,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "battery_state_of_charge",
        "address": 0x0005,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "runtime_remaining",
        "address": 0x0006,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "battery_voltage",
        "address": 0x0007,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Temperature & Load
    {
        "key": "ups_internal_temperature",
        "address": 0x0008,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "load_amps",
        "address": 0x0009,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "bad_battery_packs",
        "address": 0x000A,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "total_battery_packs",
        "address": 0x000B,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "load_percent",
        "address": 0x000C,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Output Voltage
    {
        "key": "nominal_output_voltage",
        "address": 0x000D,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "actual_output_voltage",
        "address": 0x000E,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Input Voltage & Frequency
    {
        "key": "max_input_voltage",
        "address": 0x000F,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "min_input_voltage",
        "address": 0x0010,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "input_voltage",
        "address": 0x0011,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "input_frequency",
        "address": 0x0012,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Environmental Probes (discontinued Measure-UPS)
    {
        "key": "measure_ups_temp_probe1",
        "address": 0x0013,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "measure_ups_humidity_probe1",
        "address": 0x0014,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "measure_ups_temp_probe2",
        "address": 0x0015,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "measure_ups_humidity_probe2",
        "address": 0x0016,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "measure_ups_contact_position",
        "address": 0x0017,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # 0x0018-0x0019 (offsets 24-25) are Reserved and will fail per vendor spec
    # Battery Configuration
    {
        "key": "minimum_return_battery_capacity",
        "address": 0x001A,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "lower_transfer_point",
        "address": 0x001B,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "upper_transfer_point",
        "address": 0x001C,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "nominal_output_voltage_setting",
        "address": 0x001D,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "shutdown_delay",
        "address": 0x001E,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "low_battery_duration",
        "address": 0x001F,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "turn_on_delay",
        "address": 0x0020,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "sensitivity",
        "address": 0x0021,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # UPS Identification (8 ASCII characters)
    {
        "key": "ups_id",
        "address": 0x0022,
        "count": 8,
        "type": "ascii",
        "scale": 1,
        "ascii_width": 1,
    },
    # Status Word 4 (extended faults)
    {
        "key": "status_word_4",
        "address": 0x002A,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Status Word 5 (extended faults)
    {
        "key": "status_word_5",
        "address": 0x002B,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Battery Voltage Information
    {
        "key": "nominal_battery_voltage",
        "address": 0x002C,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    {
        "key": "actual_battery_voltage",
        "address": 0x002D,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Three-phase specific (if applicable)
    {
        "key": "utility_input_voltage_phase_a",
        "address": 0x002E,
        "count": 1,
        "type": "uint16",
        "scale": 1,
    },
    # Battery Current (last valid register before reserved)
    {
        "key": "battery_current",
        "address": 0x004D,
        "count": 1,
        "type": "int16",
        "scale": 1,
    },
]

# Block read configuration for optimized polling
REGISTER_BLOCKS = [
    {
        "name": "status_battery_io",
        "start_address": 0x0000,
        "count": 24,
        "registers": [
            0x0000,
            0x0001,
            0x0002,
            0x0003,
            0x0004,
            0x0005,
            0x0006,
            0x0007,
            0x0008,
            0x0009,
            0x000A,
            0x000B,
            0x000C,
            0x000D,
            0x000E,
            0x000F,
            0x0010,
            0x0011,
            0x0012,
            0x0013,
            0x0014,
            0x0015,
            0x0016,
            0x0017,
        ],
    },
    {
        "name": "config_id_extended",
        "start_address": 0x001A,
        "count": 21,
        "registers": [
            0x001A,
            0x001B,
            0x001C,
            0x001D,
            0x001E,
            0x001F,
            0x0020,
            0x0021,
            0x0022,
            0x0023,
            0x0024,
            0x0025,
            0x0026,
            0x0027,
            0x0028,
            0x0029,
            0x002A,
            0x002B,
            0x002C,
            0x002D,
            0x002E,
        ],
    },
    {
        "name": "battery_current",
        "start_address": 0x004D,
        "count": 1,
        "registers": [0x004D],
    },
]

# Lookup map: address -> descriptor
REGISTER_MAP = {reg["address"]: reg for reg in REGISTERS}


def get_sensor_descriptions(capabilities: dict = None):
    """Get sensor descriptions for Smart-UPS device.

    Args:
        capabilities: Device capabilities (unused for Smart-UPS, included for interface compatibility)

    Returns:
        List of sensor descriptions
    """
    # Import here to avoid circular imports
    from .const import APCModbusSensorDescription, SensorStateClass

    return [
        # Battery Sensors
        APCModbusSensorDescription(
            key="battery_state_of_charge",
            name="Battery State of Charge",
            native_unit_of_measurement="%",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="battery_state_of_charge",
        ),
        APCModbusSensorDescription(
            key="battery_voltage",
            name="Battery Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="battery_voltage",
        ),
        APCModbusSensorDescription(
            key="runtime_remaining",
            name="Runtime Remaining",
            native_unit_of_measurement="min",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="runtime_remaining",
        ),
        APCModbusSensorDescription(
            key="ups_internal_temperature",
            name="UPS Internal Temperature",
            native_unit_of_measurement="°C",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="ups_internal_temperature",
        ),
        APCModbusSensorDescription(
            key="bad_battery_packs",
            name="Bad Battery Packs",
            native_unit_of_measurement="",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="bad_battery_packs",
        ),
        APCModbusSensorDescription(
            key="total_battery_packs",
            name="Total Battery Packs",
            native_unit_of_measurement="",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="total_battery_packs",
        ),
        # Load Sensors
        APCModbusSensorDescription(
            key="load_amps",
            name="Load Current",
            native_unit_of_measurement="A",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="load_amps",
        ),
        APCModbusSensorDescription(
            key="load_percent",
            name="Load Percent",
            native_unit_of_measurement="%",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="load_percent",
        ),
        # Input Sensors
        APCModbusSensorDescription(
            key="input_voltage",
            name="Input Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="input_voltage",
        ),
        APCModbusSensorDescription(
            key="input_frequency",
            name="Input Frequency",
            native_unit_of_measurement="Hz",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="input_frequency",
        ),
        APCModbusSensorDescription(
            key="max_input_voltage",
            name="Max Input Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="max_input_voltage",
        ),
        APCModbusSensorDescription(
            key="min_input_voltage",
            name="Min Input Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="min_input_voltage",
        ),
        # Output Sensors
        APCModbusSensorDescription(
            key="actual_output_voltage",
            name="Output Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="actual_output_voltage",
        ),
        APCModbusSensorDescription(
            key="nominal_output_voltage",
            name="Nominal Output Voltage",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="nominal_output_voltage",
        ),
        # Configuration Sensors
        APCModbusSensorDescription(
            key="lower_transfer_point",
            name="Lower Transfer Point",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="lower_transfer_point",
        ),
        APCModbusSensorDescription(
            key="upper_transfer_point",
            name="Upper Transfer Point",
            native_unit_of_measurement="V",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="upper_transfer_point",
        ),
        APCModbusSensorDescription(
            key="shutdown_delay",
            name="Shutdown Delay",
            native_unit_of_measurement="s",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="shutdown_delay",
        ),
        APCModbusSensorDescription(
            key="low_battery_duration",
            name="Low Battery Duration",
            native_unit_of_measurement="min",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="low_battery_duration",
        ),
        APCModbusSensorDescription(
            key="turn_on_delay",
            name="Turn On Delay",
            native_unit_of_measurement="s",
            state_class=SensorStateClass.MEASUREMENT,
            register_key="turn_on_delay",
        ),
        # Identification
        APCModbusSensorDescription(
            key="ups_id",
            name="UPS ID",
            register_key="ups_id",
            state_class=None,
        ),
    ]


def get_binary_sensor_descriptions(capabilities: dict = None):
    """Get binary sensor descriptions for Smart-UPS device.

    Args:
        capabilities: Device capabilities (unused for Smart-UPS, included for interface compatibility)

    Returns:
        List of binary sensor descriptions
    """
    # Import here to avoid circular imports
    from .const import APCModbusBinarySensorDescription, BinarySensorDeviceClass

    return [
        # Status Word 1 - Faults
        APCModbusBinarySensorDescription(
            key="ups_on_battery_low_shutdown",
            name="Low Battery Shutdown",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_1",
            bit_index=0,
        ),
        APCModbusBinarySensorDescription(
            key="ups_unable_transfer_overload",
            name="Unable to Transfer (Overload)",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_1",
            bit_index=1,
        ),
        APCModbusBinarySensorDescription(
            key="ups_main_relay_fault",
            name="Main Relay Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_1",
            bit_index=2,
        ),
        APCModbusBinarySensorDescription(
            key="ups_battery_charger_fault",
            name="Battery Charger Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_1",
            bit_index=5,
        ),
        APCModbusBinarySensorDescription(
            key="ups_temperature_fault",
            name="Temperature Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_1",
            bit_index=7,
        ),
        # Status Word 2 - Faults
        APCModbusBinarySensorDescription(
            key="ups_bypass_fault",
            name="Bypass Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_2",
            bit_index=4,
        ),
        APCModbusBinarySensorDescription(
            key="ups_inverter_fault",
            name="Inverter Fault",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_2",
            bit_index=7,
        ),
        # Status Word 3 - Operating Status
        APCModbusBinarySensorDescription(
            key="ups_online",
            name="UPS Online",
            device_class=BinarySensorDeviceClass.POWER,
            register_key="status_word_3",
            bit_index=3,
        ),
        APCModbusBinarySensorDescription(
            key="ups_on_battery",
            name="UPS On Battery",
            device_class=BinarySensorDeviceClass.POWER,
            register_key="status_word_3",
            bit_index=4,
        ),
        APCModbusBinarySensorDescription(
            key="ups_overload",
            name="UPS Overload",
            device_class=BinarySensorDeviceClass.PROBLEM,
            register_key="status_word_3",
            bit_index=5,
        ),
        APCModbusBinarySensorDescription(
            key="ups_low_battery",
            name="UPS Low Battery",
            device_class=BinarySensorDeviceClass.BATTERY,
            register_key="status_word_3",
            bit_index=6,
        ),
        APCModbusBinarySensorDescription(
            key="ups_replace_battery",
            name="UPS Replace Battery",
            device_class=BinarySensorDeviceClass.BATTERY,
            register_key="status_word_3",
            bit_index=7,
        ),
    ]
